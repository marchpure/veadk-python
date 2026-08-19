import { ArrowUp, ChevronDown, Database, Loader2, Network, RefreshCw, ShieldCheck, Sparkles } from "lucide-react";
import { useMemo, useRef } from "react";

import { DashboardPreviewPanel } from "./DashboardPreviewPanel";
import { MessageComponent } from "./Message";
import { ResizableSplitPanel } from "./ResizableSplitPanel";
import { SemanticEvidencePanel } from "./SemanticEvidencePanel";
import { TableMentionInput } from "./TableMentionInput";
import type {
  ByaanDashboardOption,
  ByaanDashboardPreviewModel,
  ByaanNotebookMessage,
  ByaanSemanticModelOption,
  ByaanSemanticQueryResultEvent,
} from "./types";

export function ByaanNotebook({
  models,
  selectedModelId,
  onModelChange,
  dashboards,
  selectedDashboardId,
  onDashboardChange,
  messages,
  input,
  onInputChange,
  onSubmit,
  examples,
  onExampleSelect,
  semanticQueryResult,
  dashboardPreview,
  busyQuery,
  busyBuild,
  onCreateDashboard,
  createDashboardDisabled,
  createDashboardDisabledReason,
  onRefresh,
  onFullscreen,
  blocked,
}: {
  models: ByaanSemanticModelOption[];
  selectedModelId: string;
  onModelChange: (value: string) => void;
  dashboards: ByaanDashboardOption[];
  selectedDashboardId: string;
  onDashboardChange: (value: string) => void;
  messages: ByaanNotebookMessage[];
  input: string;
  onInputChange: (value: string) => void;
  onSubmit: () => void;
  examples: string[];
  onExampleSelect: (value: string) => void;
  semanticQueryResult: ByaanSemanticQueryResultEvent | null;
  dashboardPreview: ByaanDashboardPreviewModel;
  busyQuery: boolean;
  busyBuild: boolean;
  onCreateDashboard: () => void;
  createDashboardDisabled?: boolean;
  createDashboardDisabledReason?: string;
  onRefresh: () => void;
  onFullscreen: () => void;
  blocked: boolean;
}) {
  const selectedModel = useMemo(
    () => models.find((model) => model.id === selectedModelId),
    [models, selectedModelId],
  );
  const hasConversation = messages.length > 0;

  if (!hasConversation) {
    return (
      <section className="byaan-notebook-source-port byaan-notebook-portal" data-testid="ask-dashboard-workbench" data-source-port="byaan-notebook">
        <NotebookHeader
          models={models}
          selectedModel={selectedModel}
          selectedModelId={selectedModelId}
          onModelChange={onModelChange}
          dashboards={dashboards}
          selectedDashboardId={selectedDashboardId}
          onDashboardChange={onDashboardChange}
          onRefresh={onRefresh}
          locked={busyQuery}
        />
        <div className="flex min-h-[560px] flex-1 items-center justify-center px-4 py-12">
          <div className="mx-auto flex w-full max-w-3xl flex-col items-center gap-5 text-center">
            <div className="inline-flex items-center gap-2 rounded-full border border-[#e4e4e7] bg-white px-3 py-1 text-xs text-[#4f5159]">
              <Sparkles className="h-3.5 w-3.5 text-[#0081f2]" />
              Governed AskData notebook
            </div>
            <div>
              <h1 className="text-3xl font-semibold tracking-tight text-[#18181b] sm:text-4xl">What do you need to know?</h1>
              <p className="mt-3 text-sm leading-6 text-[#707078]">
                Ask questions against published Semantic Skills. SQL, metric definitions, freshness, lineage, and permission evidence stay attached to every answer.
              </p>
            </div>
            <NotebookComposer
              value={input}
              onChange={onInputChange}
              onSubmit={onSubmit}
              models={models}
              selectedModelId={selectedModelId}
              onModelChange={onModelChange}
              disabled={blocked || busyQuery}
              busy={busyQuery}
              placeholder={blocked ? "Publish a Semantic Skill before asking data questions" : "Ask a business question about the published metrics..."}
              portal
            />
            <div className="flex flex-wrap justify-center gap-2" aria-label="Example questions">
              {examples.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => onExampleSelect(example)}
                  disabled={blocked}
                  className="rounded-full border border-[#e4e4e7] bg-white px-3 py-1.5 text-xs text-[#4f5159] hover:border-[#0081f2]/40 hover:text-[#18181b] disabled:opacity-50"
                >
                  {example}
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="byaan-notebook-source-port byaan-notebook-workspace" data-testid="ask-dashboard-workbench" data-source-port="byaan-notebook">
      <NotebookHeader
        models={models}
        selectedModel={selectedModel}
        selectedModelId={selectedModelId}
        onModelChange={onModelChange}
        dashboards={dashboards}
        selectedDashboardId={selectedDashboardId}
        onDashboardChange={onDashboardChange}
        onRefresh={onRefresh}
        locked={busyQuery}
      />
      <ResizableSplitPanel
        defaultLeftWidth={48}
        minLeftWidth={34}
        maxLeftWidth={66}
        leftPanel={
          <div className="flex h-full min-h-0 flex-col bg-[#181818]">
            <MessageList messages={messages} busy={busyQuery} />
            <SemanticEvidencePanel
              event={semanticQueryResult}
              dashboardAvailable={Boolean(dashboardPreview.processedHtmlContent)}
              busy={busyBuild}
              onCreateDashboard={onCreateDashboard}
              createDashboardDisabled={createDashboardDisabled}
              createDashboardDisabledReason={createDashboardDisabledReason}
            />
            <div className="flex-shrink-0 border-t border-[#2a2a2a] bg-[#181818] p-3">
              <NotebookComposer
                value={input}
                onChange={onInputChange}
                onSubmit={onSubmit}
                models={models}
                selectedModelId={selectedModelId}
                onModelChange={onModelChange}
                disabled={blocked || busyQuery}
                busy={busyQuery}
                placeholder="Ask a follow-up..."
              />
            </div>
          </div>
        }
        rightPanel={
          <DashboardPreviewPanel
            preview={dashboardPreview}
            onRefresh={onRefresh}
            onOpenFullscreen={onFullscreen}
            onBuildDashboard={onCreateDashboard}
            buildDashboardDisabled={createDashboardDisabled}
            buildDashboardDisabledReason={createDashboardDisabledReason}
          />
        }
      />
    </section>
  );
}

function NotebookHeader({
  models,
  selectedModel,
  selectedModelId,
  onModelChange,
  dashboards,
  selectedDashboardId,
  onDashboardChange,
  onRefresh,
  locked,
}: {
  models: ByaanSemanticModelOption[];
  selectedModel?: ByaanSemanticModelOption;
  selectedModelId: string;
  onModelChange: (value: string) => void;
  dashboards: ByaanDashboardOption[];
  selectedDashboardId: string;
  onDashboardChange: (value: string) => void;
  onRefresh: () => void;
  locked: boolean;
}) {
  return (
    <header className="byaan-notebook-header flex h-14 flex-shrink-0 items-center justify-between border-b border-[#e4e4e7] bg-white px-4">
      <div className="flex min-w-0 items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-[#0081f2]/10 text-[#0081f2]">
          <Database className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <strong className="block truncate text-sm font-semibold text-[#18181b]">AskTable</strong>
          <small className="block truncate text-xs text-[#707078]">Governed semantic query workspace</small>
        </div>
      </div>
      <div className="flex min-w-0 items-center gap-2">
        <SemanticModelPicker
          models={models}
          selectedModel={selectedModel}
          value={selectedModelId}
          locked={locked}
          onChange={onModelChange}
        />
        {dashboards.length ? (
          <select
            aria-label="Dashboard Skill"
            value={selectedDashboardId}
            onChange={(event) => onDashboardChange(event.target.value)}
            className="h-8 max-w-[14rem] rounded-md border border-[#d4d4d8] bg-white px-2.5 text-xs text-[#18181b]"
          >
            <option value="">Latest dashboard</option>
            {dashboards.map((dashboard) => (
              <option key={dashboard.id} value={dashboard.id}>{dashboard.name} · {dashboard.version || "v1"}</option>
            ))}
          </select>
        ) : null}
        <button type="button" onClick={onRefresh} className="flex h-8 items-center gap-1.5 rounded-md border border-[#d4d4d8] bg-white px-2.5 text-xs text-[#4f5159] hover:bg-[#f4f4f5]">
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </button>
      </div>
    </header>
  );
}

function SemanticModelPicker({
  models,
  selectedModel,
  value,
  locked,
  onChange,
}: {
  models: ByaanSemanticModelOption[];
  selectedModel?: ByaanSemanticModelOption;
  value: string;
  locked: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <div className="relative flex min-w-0 items-center gap-2">
      <div className="relative min-w-0">
        <Network className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#0081f2]" />
        <select
          aria-label="Semantic Model"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={locked || models.length === 0}
          className="h-8 w-[min(17rem,calc(100vw-6rem))] appearance-none truncate rounded-md border border-[#d4d4d8] bg-white py-0 pl-8 pr-8 text-xs text-[#18181b] outline-none hover:border-[#c7c7cc] focus:border-[#0081f2]/70 disabled:cursor-not-allowed disabled:opacity-70 sm:w-[clamp(11rem,24vw,17rem)]"
        >
          <option value="">{models.length ? "Select Semantic Model" : "No published models"}</option>
          {models.map((model) => (
            <option key={model.id} value={model.id}>{model.name} · {model.publishedVersion || "v1"}</option>
          ))}
        </select>
        <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#707078]" />
      </div>
      {selectedModel ? (
        <span className="hidden items-center gap-1 text-[11px] text-[#707078] xl:flex">
          <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />
          Published {selectedModel.publishedVersion || "v1"}
        </span>
      ) : null}
    </div>
  );
}

function MessageList({ messages, busy }: { messages: ByaanNotebookMessage[]; busy: boolean }) {
  const endRef = useRef<HTMLDivElement>(null);
  return (
    <div className="min-h-0 flex-1 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      <div className="mx-auto w-full max-w-3xl space-y-3 px-4 py-6 sm:px-6 min-[1440px]:max-w-4xl min-[2560px]:max-w-[1400px]">
        {messages.map((message) => <MessageComponent key={message.id} message={message} />)}
        {busy ? <div className="text-xs text-[#888888]">Thinking</div> : null}
        <div ref={endRef} />
      </div>
    </div>
  );
}

function NotebookComposer({
  value,
  onChange,
  onSubmit,
  models,
  selectedModelId,
  onModelChange,
  disabled,
  busy,
  placeholder,
  portal = false,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  models: ByaanSemanticModelOption[];
  selectedModelId: string;
  onModelChange: (value: string) => void;
  disabled: boolean;
  busy: boolean;
  placeholder: string;
  portal?: boolean;
}) {
  return (
    <form
      className={`byaan-table-mention-composer w-full overflow-hidden rounded-2xl border border-[#d4d4d8] bg-white shadow-sm ${portal ? "max-w-3xl" : ""}`}
      onSubmit={(event) => {
        event.preventDefault();
        if (!disabled && value.trim()) onSubmit();
      }}
    >
      <TableMentionInput
        value={value}
        onValueChange={onChange}
        onSubmit={() => {
          if (!disabled && value.trim()) onSubmit();
        }}
        disabled={disabled || busy}
        placeholder={placeholder}
        singleLine={!portal}
      />
      <div className="flex items-center justify-between gap-3 border-t border-[#e4e4e7] px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <select
            aria-label="Semantic Skill"
            value={selectedModelId}
            onChange={(event) => onModelChange(event.target.value)}
            disabled={!models.length || busy}
            className="h-8 max-w-[15rem] rounded-md border border-[#d4d4d8] bg-white px-2.5 text-xs text-[#18181b]"
          >
            {models.length ? null : <option value="">No Semantic Model</option>}
            {models.map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}
          </select>
        </div>
        <button
          type="submit"
          disabled={disabled || busy || !value.trim()}
          className="flex h-9 w-9 items-center justify-center rounded-full bg-[#0081f2] text-white transition-colors hover:bg-[#006adc] disabled:cursor-not-allowed disabled:opacity-50"
          aria-label="Send"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
        </button>
      </div>
    </form>
  );
}
